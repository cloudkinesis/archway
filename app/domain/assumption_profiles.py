from enum import Enum


class AssumptionProfile(str, Enum):
    CONSERVATIVE_POC = "conservative_poc"
    BALANCED_PRODUCTION = "balanced_production"
    HIGH_SCALE_PRODUCTION = "high_scale_production"


INDUSTRIAL_IOT_DEFAULT_ASSUMPTIONS = {
    "telemetry_frequency_seconds": {"low": 300, "expected": 60, "high": 15},
    "payload_kb": {"low": 1, "expected": 2, "high": 5},
    "aggregation_window_seconds": {"low": 300, "expected": 300, "high": 60},
    "candidate_anomaly_rate_percent": {"low": 0.01, "expected": 0.1, "high": 1.0},
    "confirmed_incident_rate_percent": {"low": 0.001, "expected": 0.01, "high": 0.1},
}

