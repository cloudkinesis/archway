UTILITY_GRID = (
    "A national electric utility company wants to build a predictive grid failure detection system. "
    "The platform ingests real-time sensor data from 200,000 smart meters and 15,000 distribution transformers, "
    "correlating voltage fluctuations, load imbalances, and ambient temperature readings against historical failure patterns. "
    "When the system detects a transformer approaching thermal runaway or a feeder line showing pre-fault oscillation signatures, "
    "it automatically dispatches field crews via the existing workforce management system and pre-positions replacement equipment "
    "at the nearest depot. The goal is reducing unplanned outages by 45% and cutting mean-time-to-restore from 4 hours to under "
    "90 minutes within the first 18 months of deployment."
)

GOLDEN_SCENARIOS = {
    "telecom_congestion": "Telecom operator predicts congestion from 8 billion CDRs daily, 120,000 cell towers, 15-minute prediction horizon, 2-year CDR retention, and TRAI QoS compliance.",
    "investment_risk": "Investment bank runs 2.4 million open derivatives positions across 14 exchanges, portfolio Greeks every 30 seconds, sub-second Monte Carlo VaR, SEC Rule 15c3-1, and MAS margin rules.",
    "clinical_federated": "Healthcare pharmaceutical team matches clinical trials across 40 hospital EHR systems including Epic, Cerner, Meditech, with no centralized PHI, aggregated gradients only, HIPAA, GDPR, and 21 CFR Part 11.",
    "semiconductor_twin": "Semiconductor manufacturer builds a digital twin predictive maintenance platform across 3 fabs, 2,800 tools, 500+ sensor channels per tool, 1 kHz streaming, 72-hour failure prediction, false positive below 0.1%, $2M cost per false alarm, and sub-5-second catastrophic alerting.",
    "aml_graph": "Retail banking AML analyzes 180 million transactions/day, 400 million entity nodes, 3 billion graph edges, SAR within 30 days, US BSA, UK MLR 2017, and Singapore MAS Notice 626.",
    "energy_bidding": "Energy trading optimizes 4 GW wind/solar capacity across 6 European intraday markets, 15-minute bidding cycle, 3-second inference plus bid submission, and MiFID II algorithmic trading.",
    "catastrophe_modeling": "Insurance carrier models catastrophe risk for 12 million policies, 50,000 synthetic storm tracks, portfolio rerun within 4 hours, current runtime 3 days, Solvency II, and AM Best reporting.",
    "vehicle_ota": "Autonomous vehicle fleet coordinates OTA updates for 15,000 vehicles in 8 cities with 1% to 10% to 50% to 100% rollout, 200 MB/hour telemetry per vehicle, zero downtime, and ISO 26262 ASIL-D.",
    "national_identity": "Government national identity platform handles 5 million verification requests/day, 800 million enrolled citizens, 2-second match/no-match, 50,000 concurrent requests, false acceptance below 0.001%, air-gapped deployment, no public cloud egress, national data sovereignty, and 99.999% availability.",
    "network_slicing": "Telecom 5G slice lifecycle management spans 3,000 base stations, URLLC 1ms latency, eMBB 10Gbps throughput, mMTC smart city IoT, 3GPP NRF/NSSF/SMF integration, and 3GPP Release 17.",
    "supply_chain_inventory": "Supply chain optimization uses 45 manufacturing plants, 200 distribution centers, 500,000 retail endpoints, 2 billion POS transactions/week, 18 million SKU-location combinations, 98.5% service level, and SAP S/4HANA RFC/BAPI integration.",
    "live_sports": "Media company streams 4K HDR live sports to 25 million concurrent viewers with 6-second glass-to-glass latency, 40 countries, geo-rights blackout enforcement, Widevine L1 DRM, and GDPR ad-consent.",
    "drug_graph": "Pharmaceutical drug interaction prediction scores 50 million compound pairs daily, 4 million known clinical interactions, 8-hour nightly scoring window, FDA FAERS data, FDA IND applications, and GxP validation.",
    "drone_fleet": "Logistics autonomous drone delivery fleet coordinates 2,000 drones across 15 metro areas with 10 Hz telemetry, 50m minimum separation, FAA UTM integration, FAA Part 135, and weather-triggered ground stop.",
    "market_making": "Financial markets high-frequency market making covers 8,000 instruments, 4 exchanges, 5 microsecond reaction time, FPGA acceleration, $500K drawdown kill switch, 60-second drawdown window, co-located exchange data centers, nanosecond tick-level audit trail, SEC Reg SHO, MiFID II, and FINRA 5310.",
}
