from __future__ import annotations

from app.domain.quality_findings import QualityFinding
from app.models.domain import ArchitectureComponent, ArchitectureFlow, ArchitectureSpec, AWSServiceSelection
from app.services.governance_controls import GovernanceControlEnricher


class RepairRule:
    def matches(self, findings: list[QualityFinding], spec: ArchitectureSpec) -> bool:
        raise NotImplementedError

    def apply(self, spec: ArchitectureSpec, findings: list[QualityFinding]) -> tuple[bool, str | None]:
        raise NotImplementedError


class GovernanceRepairRule(RepairRule):
    def matches(self, findings: list[QualityFinding], spec: ArchitectureSpec) -> bool:
        return any(item.category == "governance" and item.auto_repairable for item in findings)

    def apply(self, spec: ArchitectureSpec, findings: list[QualityFinding]) -> tuple[bool, str | None]:
        before = spec.model_dump()
        enriched = GovernanceControlEnricher().enrich_specs([spec])
        if enriched:
            spec.governance_controls = enriched[0].governance_controls
            spec.flows = enriched[0].flows
            spec.components = enriched[0].components
        changed = spec.model_dump() != before
        note = "Typed governance controls were auto-added and linked to effectful flows." if changed else None
        return changed, note


def _find_services_by_key(service_key: str) -> set[str]:
    from app.services.pattern_catalog import PATTERNS
    names = set()
    for wp in PATTERNS.values():
        for sp in wp.services:
            if sp.service_key == service_key:
                names.add(sp.service)
    return names


def _find_service_by_service_key(service_key: str, default_service: str) -> str:
    from app.services.pattern_catalog import PATTERNS
    for wp in PATTERNS.values():
        for sp in wp.services:
            if sp.service_key == service_key:
                return sp.service
    return default_service


class PrivateConnectivityRepairRule(RepairRule):
    def matches(self, findings: list[QualityFinding], spec: ArchitectureSpec) -> bool:
        has_finding = False
        for f in findings:
            desc = f.description.lower()
            title = f.title.lower()
            if any(term in desc or term in title for term in [
                "private network", 
                "regulated path", 
                "private path", 
                "external enterprise system", 
                "private connectivity"
            ]):
                has_finding = True
                break
                
        has_capability = "private_connectivity" in (spec.metadata or {}).get("capabilities", [])
        return has_finding or has_capability

    def apply(self, spec: ArchitectureSpec, findings: list[QualityFinding]) -> tuple[bool, str | None]:
        changed = False
        dc_services = _find_services_by_key("direct_connect")
        dc_services.add("AWS Direct Connect")
        dc_services.add("AWS Site-to-Site VPN")
        dc_services.add("AWS Direct Connect / Site-to-Site VPN")

        existing_connectivity = any(
            "connectivity" in c.id or c.service in dc_services
            for c in spec.components
        )
        dc_service = _find_service_by_service_key("direct_connect", "AWS Direct Connect")
        if not existing_connectivity:
            conn_comp = ArchitectureComponent(
                id="private_connectivity",
                name="Private Connectivity",
                service=dc_service,
                scope="regional_integration",
                logical_group="Private connectivity",
                metadata={"role": "private_connectivity"}
            )
            changed |= _add_missing_components(spec, [conn_comp])
            changed |= _add_missing_services(spec, [conn_comp])
            
            external_sources = [c for c in spec.components if c.scope == "external_actor" or "external" in c.id]
            for src in external_sources:
                flow = ArchitectureFlow(
                    id=f"flow_private_{src.id}",
                    source=src.id,
                    target="private_connectivity",
                    label=f"Deliver private traffic from {src.name}",
                    protocol="HTTPS",
                    metadata={"classification": "private_integration"}
                )
                changed |= _add_missing_flows(spec, [flow])
        
        note = f"Added private connectivity ({dc_service}) and integration path." if changed else None
        if changed:
            _mark_repaired(spec, "private_connectivity_repair")
        return changed, note


class ObservabilityRepairRule(RepairRule):
    def matches(self, findings: list[QualityFinding], spec: ArchitectureSpec) -> bool:
        has_finding = any(
            any(term in f.description.lower() or term in f.title.lower() for term in ("observability", "logging", "audit", "cloudwatch", "cloudtrail"))
            for f in findings
        )
        return has_finding

    def apply(self, spec: ArchitectureSpec, findings: list[QualityFinding]) -> tuple[bool, str | None]:
        changed = False
        cw_services = _find_services_by_key("cloudwatch")
        cw_services.add("Amazon CloudWatch")
        cw_services.add("Amazon CloudWatch / Kinesis Data Streams")

        has_observability = any(
            any(term in c.service.lower() for term in ("cloudwatch", "cloudtrail")) or "audit" in c.id or c.service in cw_services
            for c in spec.components
        )
        cw_service = _find_service_by_service_key("cloudwatch", "Amazon CloudWatch")
        if not has_observability:
            obs_comp = ArchitectureComponent(
                id="cloudwatch_logs",
                name="Security and Observability Logs",
                service=cw_service,
                scope="regional_managed_data",
                logical_group="Audit and regulatory evidence",
                metadata={"role": "logging"}
            )
            changed |= _add_missing_components(spec, [obs_comp])
            changed |= _add_missing_services(spec, [obs_comp])
            
            compute_nodes = [c for c in spec.components if c.scope in ("vpc_resident", "regional_compute") and c.id != "cloudwatch_logs"]
            for comp in compute_nodes[:2]:
                flow = ArchitectureFlow(
                    id=f"flow_log_{comp.id}",
                    source=comp.id,
                    target="cloudwatch_logs",
                    label=f"Publish audit and application logs",
                    metadata={"classification": "audit_write"}
                )
                changed |= _add_missing_flows(spec, [flow])
        
        note = f"Added security/observability logging ({cw_service}) component." if changed else None
        if changed:
            _mark_repaired(spec, "observability_repair")
        return changed, note


class CapitalMarketsRiskRepairRule(RepairRule):
    def matches(self, findings: list[QualityFinding], spec: ArchitectureSpec) -> bool:
        families = set((spec.metadata or {}).get("workload_families") or [])
        return bool({"capital_markets_risk_engine", "monte_carlo_risk_grid"} & families)

    def apply(self, spec: ArchitectureSpec, findings: list[QualityFinding]) -> tuple[bool, str | None]:
        changed = _ensure_capital_markets_risk_path(spec)
        note = "added capital-markets risk compute, state/cache, private connectivity, and audit components/flows." if changed else None
        return changed, note


class PaymentFraudRepairRule(RepairRule):
    def matches(self, findings: list[QualityFinding], spec: ArchitectureSpec) -> bool:
        families = set((spec.metadata or {}).get("workload_families") or [])
        return "financial_fraud_detection" in families

    def apply(self, spec: ArchitectureSpec, findings: list[QualityFinding]) -> tuple[bool, str | None]:
        changed = _ensure_payment_fraud_path(spec)
        note = "added payment-fraud scoring, policy decisioning, analyst queue, blocking, and audit path." if changed else None
        return changed, note


class ArchitectureRepairer:
    def __init__(self) -> None:
        self.registry: list[RepairRule] = [
            GovernanceRepairRule(),
            PrivateConnectivityRepairRule(),
            ObservabilityRepairRule(),
            CapitalMarketsRiskRepairRule(),
            PaymentFraudRepairRule(),
        ]

    def repair(self, specs: list[ArchitectureSpec], findings: list[QualityFinding]) -> tuple[list[ArchitectureSpec], list[str]]:
        repaired = [spec.model_copy(deep=True) for spec in specs]
        notes: list[str] = []
        for spec in repaired:
            for rule in self.registry:
                if rule.matches(findings, spec):
                    changed, note = rule.apply(spec, findings)
                    if changed and note:
                        notes.append(f"{spec.mode}: {note}" if spec.mode else note)
        return repaired, notes


def _ensure_capital_markets_risk_path(spec: ArchitectureSpec) -> bool:
    changed = False
    additions = [
        ArchitectureComponent(id="market_feeds", name="Market Data and Exchange Feeds", service="External market data/exchange feeds", scope="external_actor", logical_group="Market data and exchange feeds", metadata={"role": "external_source"}),
        ArchitectureComponent(id="connectivity", name="Private Market Connectivity", service="AWS Direct Connect", scope="regional_integration", logical_group="Private connectivity", metadata={"role": "private_connectivity"}),
        ArchitectureComponent(id="market_stream", name="Market Data Normalization", service="Amazon MSK", scope="vpc_resident", logical_group="Streaming and position state", metadata={"role": "market_data_ingestion"}),
        ArchitectureComponent(id="portfolio_state", name="Portfolio and Position State Store", service="Amazon DynamoDB", scope="regional_managed_data", logical_group="Streaming and position state", metadata={"role": "portfolio_state_store"}),
        ArchitectureComponent(id="risk_cache", name="Low-Latency Risk Cache", service="Amazon ElastiCache", scope="vpc_resident", logical_group="Risk compute grid", metadata={"role": "low_latency_cache"}),
        ArchitectureComponent(id="risk_grid", name="Risk Compute Grid", service="AWS Batch", scope="vpc_resident", logical_group="Risk compute grid", metadata={"role": "risk_compute_grid"}),
        ArchitectureComponent(id="simulation_fs", name="Simulation Scratch Storage", service="Amazon FSx for Lustre", scope="vpc_resident", logical_group="Risk compute grid", metadata={"role": "simulation_scratch_storage"}),
        ArchitectureComponent(id="risk_lake", name="Risk Results Store", service="Amazon S3", scope="regional_managed_data", logical_group="Audit and regulatory evidence", metadata={"role": "risk_results_store"}),
        ArchitectureComponent(id="compliance_adapter", name="Pre-Trade Compliance Decision Point", service="AWS Lambda", scope="regional_compute", logical_group="Compliance decisioning", metadata={"role": "pre_trade_compliance_adapter"}),
        ArchitectureComponent(id="audit_query", name="Regulatory Audit Store", service="Amazon Athena", scope="regional_managed_data", logical_group="Audit and regulatory evidence", metadata={"role": "audit_query"}),
    ]
    flows = [
        ArchitectureFlow(id="market_private_ingest", source="market_feeds", target="connectivity", label="Deliver exchange and market data feeds", protocol="Private circuit/FIX", metadata={"classification": "private_integration"}),
        ArchitectureFlow(id="normalize_market_data", source="connectivity", target="market_stream", label="Normalize and publish market/position events", metadata={"classification": "stream_ingestion"}),
        ArchitectureFlow(id="update_position_state", source="market_stream", target="portfolio_state", label="Update portfolio and position state", metadata={"classification": "state_write"}),
        ArchitectureFlow(id="refresh_risk_cache", source="portfolio_state", target="risk_cache", label="Refresh hot Greeks, limits, and portfolio aggregates", metadata={"classification": "cache_write"}),
        ArchitectureFlow(id="start_risk_grid", source="portfolio_state", target="risk_grid", label="Start scheduled or triggered Monte Carlo VaR/Greeks run", metadata={"classification": "workflow_start"}),
        ArchitectureFlow(id="risk_scratch_io", source="risk_grid", target="simulation_fs", label="Read/write high-throughput simulation scratch data", metadata={"classification": "hpc_data_access"}),
        ArchitectureFlow(id="publish_risk_results", source="risk_grid", target="risk_cache", label="Publish sub-second risk and Greeks results", metadata={"classification": "cache_write"}),
        ArchitectureFlow(id="persist_risk_evidence", source="risk_grid", target="risk_lake", label="Persist risk results, inputs, and model/run evidence", metadata={"classification": "audit_write"}),
        ArchitectureFlow(id="pre_trade_decision", source="risk_cache", target="compliance_adapter", label="Pre-trade compliance decision and block recommendation", metadata={"classification": "trade_block"}),
        ArchitectureFlow(id="audit_query_path", source="risk_lake", target="audit_query", label="Query retained evidence for regulatory review", metadata={"classification": "analytics_query"}),
    ]
    changed |= _add_missing_components(spec, additions)
    changed |= _add_missing_flows(spec, flows)
    changed |= _add_missing_services(spec, additions)
    if changed:
        _mark_repaired(spec, "capital_markets_risk_repair")
    return changed


def _ensure_payment_fraud_path(spec: ArchitectureSpec) -> bool:
    changed = False
    before = len(spec.selected_services)
    spec.selected_services = [
        item
        for item in spec.selected_services
        if "iot" not in item.service.lower() and "sitewise" not in item.service.lower()
    ]
    changed |= len(spec.selected_services) != before
    additions = [
        ArchitectureComponent(id="stream", name="Transaction Authorization Stream", service="Amazon Kinesis Data Streams", scope="regional_integration", logical_group="Payment transaction sources", metadata={"role": "stream_ingestion"}),
        ArchitectureComponent(id="analytics", name="Feature Enrichment", service="Amazon Managed Service for Apache Flink", scope="regional_integration", logical_group="Feature enrichment", metadata={"role": "stream_processor"}),
        ArchitectureComponent(id="state", name="Low-Latency Feature Store", service="Amazon DynamoDB", scope="regional_managed_data", logical_group="Feature enrichment", metadata={"role": "feature_store"}),
        ArchitectureComponent(id="ml", name="Fraud Scoring Endpoint", service="Amazon SageMaker", scope="regional_managed_ai", logical_group="Fraud scoring", metadata={"role": "model_endpoint"}),
        ArchitectureComponent(id="policy", name="Policy Decision Engine", service="AWS Step Functions", scope="regional_orchestration", logical_group="Policy decisioning", metadata={"role": "workflow"}),
        ArchitectureComponent(id="case_queue", name="Analyst Review Queue", service="Amazon SQS", scope="regional_integration", logical_group="Analyst review and blocking", metadata={"role": "queue"}),
        ArchitectureComponent(id="audit_lake", name="S3 Object Lock Audit Trail", service="Amazon S3", scope="regional_managed_data", logical_group="Audit and compliance evidence", metadata={"role": "audit_evidence_store"}),
    ]
    flows = [
        ArchitectureFlow(id="transaction_stream", source="stream", target="analytics", label="Calculate transaction risk features", metadata={"classification": "stream_processing"}),
        ArchitectureFlow(id="score_fraud", source="analytics", target="ml", label="Score every transaction under latency target", metadata={"classification": "model_invocation"}),
        ArchitectureFlow(id="persist_case_state", source="ml", target="state", label="Persist feature, score, and case state", metadata={"classification": "state_write"}),
        ArchitectureFlow(id="analyst_review", source="ml", target="case_queue", label="Queue suspicious payments for analyst review", metadata={"classification": "queue_for_review"}),
        ArchitectureFlow(id="policy_block", source="ml", target="policy", label="Request policy approval for high-confidence block", metadata={"classification": "policy_change"}),
        ArchitectureFlow(id="audit_fraud_decision", source="policy", target="audit_lake", label="Write score, model version, and block decision evidence", metadata={"classification": "audit_write"}),
    ]
    changed |= _add_missing_components(spec, additions)
    changed |= _add_missing_flows(spec, flows)
    changed |= _add_missing_services(spec, additions)
    if changed:
        _mark_repaired(spec, "payment_fraud_repair")
    return changed


def _add_missing_components(spec: ArchitectureSpec, components: list[ArchitectureComponent]) -> bool:
    existing = {component.id for component in spec.components}
    additions = [component for component in components if component.id not in existing]
    spec.components.extend(additions)
    return bool(additions)


def _add_missing_flows(spec: ArchitectureSpec, flows: list[ArchitectureFlow]) -> bool:
    existing = {flow.id for flow in spec.flows}
    additions = [flow for flow in flows if flow.id not in existing and flow.source in {item.id for item in spec.components} and flow.target in {item.id for item in spec.components}]
    spec.flows.extend(additions)
    return bool(additions)


def _add_missing_services(spec: ArchitectureSpec, components: list[ArchitectureComponent]) -> bool:
    existing = {item.service.lower() for item in spec.selected_services}
    additions = [
        AWSServiceSelection(service=component.service, purpose=component.name, rationale="Added by deterministic architecture repair.")
        for component in components
        if component.service.lower() not in existing and not component.service.lower().startswith("external ")
    ]
    spec.selected_services.extend(additions)
    return bool(additions)


def _mark_repaired(spec: ArchitectureSpec, repair_name: str) -> None:
    repairs = list((spec.metadata or {}).get("convergence_repairs") or [])
    if repair_name not in repairs:
        repairs.append(repair_name)
    spec.metadata = {**spec.metadata, "convergence_repairs": repairs}
