import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class MetricValue:
    value: float
    unit: str
    raw: str
    derived: bool = False


@dataclass
class ExtractedMetrics:
    asset_counts: dict[str, MetricValue] = field(default_factory=dict)
    business_targets: dict[str, MetricValue] = field(default_factory=dict)
    telemetry_signals: list[str] = field(default_factory=list)
    detection_targets: list[str] = field(default_factory=list)
    operational_actions: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)

    def model_dump(self) -> dict:
        return {
            "asset_counts": {key: value.__dict__ for key, value in self.asset_counts.items()},
            "business_targets": {key: value.__dict__ for key, value in self.business_targets.items()},
            "telemetry_signals": self.telemetry_signals,
            "detection_targets": self.detection_targets,
            "operational_actions": self.operational_actions,
            "assumptions": self.assumptions,
        }


def extract_metrics(text: str) -> ExtractedMetrics:
    lower = text.lower()
    result = ExtractedMetrics()
    _put_match(result.asset_counts, "fabs", "count", text, r"(?P<value>\d[\d,]*)\s+fabs?")
    _put_match(result.asset_counts, "manufacturing_tools", "count", text, r"(?P<value>\d[\d,]*)\s+tools?")
    _put_match(result.asset_counts, "cell_towers", "count", text, r"(?P<value>\d[\d,]*)\s+cell towers?")
    _put_match(result.asset_counts, "hospital_count", "count", text, r"(?P<value>\d[\d,]*)\s+hospitals?")
    _put_match(result.asset_counts, "operating_room_count", "count", text, r"(?P<value>\d[\d,]*)\s+operating rooms?")
    _put_match(result.asset_counts, "camera_towers", "count", text, r"(?P<value>\d[\d,]*)\s+(?:remote\s+|lookout\s+)?camera towers?")
    _put_match(result.asset_counts, "underwater_cameras", "count", text, r"(?P<value>\d[\d,]*)\s+underwater cameras?")
    _put_match(result.asset_counts, "fish_cages", "count", text, r"(?P<value>\d[\d,]*)\s+(?:sea\s+)?cages?")
    _put_match(result.asset_counts, "staff_users", "count", text, r"(?P<value>\d[\d,]*)\s+(?:farm\s+staff|staff|responder)\s+users?")
    _put_match(result.asset_counts, "resident_alert_recipients", "count", text, r"(?P<value>\d[\d,]*)\s+residents?\s+for\s+alerts?")
    _put_match(result.asset_counts, "historical_contract_count", "count", text, r"(?P<value>\d[\d,]*)\s+historical contracts?")
    if "historical_contract_count" not in result.asset_counts:
        _put_match(result.asset_counts, "document_count", "count", text, r"(?P<value>\d[\d,]*)\s+(?:documents?|contracts?|agreements?)")
    _put_match(result.asset_counts, "open_derivatives_positions", "count", text, r"(?P<value>\d+(?:\.\d+)?)\s*million\s+open derivatives positions?")
    _put_match(result.asset_counts, "exchanges", "count", text, r"(?P<value>\d[\d,]*)\s+exchanges?")
    _put_match(result.business_targets, "cdrs_per_day", "events_per_day", text, r"(?P<value>\d+(?:\.\d+)?)\s*billion\s+cdrs?\s+daily")
    _put_match(result.business_targets, "prediction_horizon_minutes", "minutes", text, r"(?P<value>\d+(?:\.\d+)?)\s*[- ]?minute\s+prediction horizon")
    _put_match(result.business_targets, "retention_years", "years", text, r"(?P<value>\d+(?:\.\d+)?)\s*[- ]?year\s+(?:cdr\s+)?retention")
    _put_match(result.business_targets, "transactions_per_day", "transactions_per_day", text, r"(?P<value>\d+(?:\.\d+)?)\s*(?P<scale>million|billion)?\s+(?:card\s+|payment\s+)?transactions?\s+(?:per\s+day|/day|daily)")
    _put_match(result.business_targets, "latency_target_ms", "milliseconds", text, r"(?:under|within|below|less than)\s+(?P<value>\d+(?:\.\d+)?)\s*(?:ms|milliseconds?)")
    _put_match(result.business_targets, "audit_retention_years", "years", text, r"(?P<value>\d+(?:\.\d+)?)\s*[- ]?year\s+audit\s+(?:evidence\s+)?retention")
    if "audit_retention_years" not in result.business_targets:
        _put_match(result.business_targets, "audit_retention_years", "years", text, r"retain\s+audit\s+(?:evidence\s+)?for\s+(?P<value>\d+(?:\.\d+)?)\s+years?")
    if "audit_retention_years" not in result.business_targets:
        word_years = re.search(r"retain\s+audit\s+(?:evidence\s+)?for\s+(?P<value>one|two|three|four|five|six|seven|eight|nine|ten)\s+years?", text, flags=re.I)
        if word_years:
            raw = word_years.group(0).strip()
            result.business_targets["audit_retention_years"] = MetricValue(float(_WORD_NUMBERS[word_years.group("value").lower()]), "years", raw)
    _put_match(result.business_targets, "false_positive_reduction_target_percent", "percent", text, r"(?:reduce|reducing|reduction in|cut)\s+false positives?\s+by\s+(?P<value>\d+(?:\.\d+)?)\s*percent")
    if "false_positive_reduction_target_percent" not in result.business_targets:
        _put_match(result.business_targets, "false_positive_reduction_target_percent", "percent", text, r"false positives?\s+(?:reduction|reduced)\s+(?:target\s+)?(?:by\s+)?(?P<value>\d+(?:\.\d+)?)\s*%")
    _put_match(result.business_targets, "greeks_frequency_seconds", "seconds", text, r"greeks every (?P<value>\d+(?:\.\d+)?)\s+seconds?")
    if re.search(r"sub[- ]second\s+monte carlo var", text, flags=re.I):
        result.business_targets["sub_second_var_latency"] = MetricValue(1.0, "seconds", "sub-second Monte Carlo VaR")
    _put_match(result.business_targets, "sensor_channels_per_tool", "channels_per_tool", text, r"(?P<value>\d[\d,]*)\+?\s+sensor channels?\s+per\s+tool")
    _put_match(result.business_targets, "streaming_sample_rate_khz", "khz", text, r"(?P<value>\d+(?:\.\d+)?)\s*khz")
    _put_match(result.business_targets, "prediction_horizon_hours", "hours", text, r"(?P<value>\d+(?:\.\d+)?)\s*[- ]?hour\s+(?:failure\s+)?prediction")
    _put_match(result.business_targets, "false_positive_target_percent", "percent", text, r"false positive (?:rate )?(?:below|under)\s+(?P<value>\d+(?:\.\d+)?)%")
    _put_match(result.business_targets, "false_alarm_cost_usd", "usd", text, r"\$(?P<value>\d+(?:\.\d+)?)\s*m(?:illion)?\s+cost per false alarm")
    _put_match(result.business_targets, "catastrophic_alert_latency_seconds", "seconds", text, r"sub[- ](?P<value>\d+(?:\.\d+)?)\s*[- ]?second")
    _put_match(result.business_targets, "concurrent_viewers", "viewers", text, r"(?P<value>\d+(?:\.\d+)?)\s*million\s+concurrent viewers?")
    _put_match(result.business_targets, "glass_to_glass_latency_seconds", "seconds", text, r"(?P<value>\d+(?:\.\d+)?)\s*[- ]?second\s+glass[- ]to[- ]glass latency")
    _put_match(result.business_targets, "refresh_cadence_minutes", "minutes", text, r"(?:refresh|predictions? must refresh|predictions? refresh)[^\d]{0,40}(?:every\s+)?(?P<value>\d+(?:\.\d+)?)\s+minutes?")
    if "refresh_cadence_minutes" not in result.business_targets:
        _put_match(result.business_targets, "refresh_cadence_minutes", "minutes", text, r"predictions?[^\d]{0,30}every\s+(?P<value>\d+(?:\.\d+)?)\s+minutes?")
    if "refresh_cadence_minutes" not in result.business_targets:
        _put_match(result.business_targets, "refresh_cadence_minutes", "minutes", text, r"(?P<value>\d+(?:\.\d+)?)\s*[- ]?minute\s+(?:prediction\s+)?refresh")
    if "refresh_cadence_minutes" not in result.business_targets:
        _put_match(result.business_targets, "refresh_cadence_minutes", "minutes", text, r"imagery\s+refresh\s+every\s+(?P<value>\d+(?:\.\d+)?)\s+minutes?")
    if "refresh_cadence_minutes" not in result.business_targets:
        _put_match(result.business_targets, "refresh_cadence_minutes", "minutes", text, r"readings?\s+every\s+(?P<value>\d+(?:\.\d+)?)\s+minutes?")
    _put_match(result.business_targets, "telemetry_frequency_seconds", "seconds", text, r"(?:sensor\s+)?readings?\s+every\s+(?P<value>\d+(?:\.\d+)?)\s+seconds?")
    _put_match(result.business_targets, "imagery_windows_per_day", "windows_per_day", text, r"(?P<value>\d[\d,]*)\s+(?:satellite/)?imagery\s+refresh\s+windows?\s+per\s+day")
    _put_match(result.business_targets, "scheduled_surgeries_per_day", "surgeries_per_day", text, r"(?P<value>\d[\d,]*)\s+(?:scheduled\s+)?surgeries\s+(?:per\s+day|/day|daily)")
    _put_match(result.business_targets, "country_count", "countries", text, r"(?P<value>\d[\d,]*)\s+countries")
    _put_match(result.asset_counts, "smart_meters", "count", text, r"(?P<value>\d[\d,]*)\s+smart meters?")
    _put_match(result.asset_counts, "distribution_transformers", "count", text, r"(?P<value>\d[\d,]*)\s+distribution transformers?")
    if "distribution_transformers" not in result.asset_counts:
        _put_match(result.asset_counts, "transformers", "count", text, r"(?P<value>\d[\d,]*)\s+transformers?")
    _put_match(result.business_targets, "unplanned_outage_reduction_percent", "percent", text, r"reduc(?:e|es|ing)\s+unplanned outages by (?P<value>\d+(?:\.\d+)?)%")
    _put_match(result.business_targets, "current_mttr_hours", "hours", text, r"mean[- ]time[- ]to[- ]restore from (?P<value>\d+(?:\.\d+)?)\s+hours?")
    _put_match(result.business_targets, "target_mttr_minutes", "minutes", text, r"under (?P<value>\d+(?:\.\d+)?)\s+minutes?")
    _put_match(result.business_targets, "target_timeline_months", "months", text, r"within the first (?P<value>\d+(?:\.\d+)?)\s+months?")
    if "false_alarm_cost_usd" in result.business_targets and re.search(r"\$\d+(?:\.\d+)?\s*m(?:illion)?", lower):
        cost = result.business_targets["false_alarm_cost_usd"]
        result.business_targets["false_alarm_cost_usd"] = MetricValue(cost.value * 1_000_000, cost.unit, cost.raw)
    if "open_derivatives_positions" in result.asset_counts:
        positions = result.asset_counts["open_derivatives_positions"]
        if "million" in positions.raw.lower():
            result.asset_counts["open_derivatives_positions"] = MetricValue(positions.value * 1_000_000, positions.unit, positions.raw)
    if "cdrs_per_day" in result.business_targets:
        cdrs = result.business_targets["cdrs_per_day"]
        if "billion" in cdrs.raw.lower():
            result.business_targets["cdrs_per_day"] = MetricValue(cdrs.value * 1_000_000_000, cdrs.unit, cdrs.raw)
    if "concurrent_viewers" in result.business_targets:
        viewers = result.business_targets["concurrent_viewers"]
        if "million" in viewers.raw.lower():
            result.business_targets["concurrent_viewers"] = MetricValue(viewers.value * 1_000_000, viewers.unit, viewers.raw)
    if "transactions_per_day" in result.business_targets:
        transactions = result.business_targets["transactions_per_day"]
        lower_raw = transactions.raw.lower()
        value = transactions.value
        if "billion" in lower_raw:
            value *= 1_000_000_000
        elif "million" in lower_raw:
            value *= 1_000_000
        result.business_targets["transactions_per_day"] = MetricValue(value, transactions.unit, transactions.raw)
        result.business_targets["average_tps"] = MetricValue(round(value / 86400, 2), "transactions_per_second", "transactions_per_day / 86400", derived=True)
    total_assets = sum(int(item.value) for key, item in result.asset_counts.items() if key != "fabs")
    if total_assets:
        result.asset_counts["total_monitored_assets"] = MetricValue(float(total_assets), "count", "sum of monitored asset counts", derived=True)
    tools = result.asset_counts.get("manufacturing_tools")
    channels = result.business_targets.get("sensor_channels_per_tool")
    sample_rate = result.business_targets.get("streaming_sample_rate_khz")
    if tools and channels and sample_rate:
        samples_per_second = tools.value * channels.value * sample_rate.value * 1000
        result.business_targets["raw_sensor_samples_per_second"] = MetricValue(
            samples_per_second,
            "samples_per_second",
            "manufacturing_tools * sensor_channels_per_tool * streaming_sample_rate_khz * 1000",
            derived=True,
        )
    signal_markers = {
        "voltage_fluctuations": ("voltage fluctuation", "voltage fluctuations", "voltage"),
        "load_imbalances": ("load imbalance", "load imbalances"),
        "ambient_temperature": ("ambient temperature", "temperature reading"),
        "oscillation_signatures": ("oscillation", "oscillation signatures"),
        "sensor_channels": ("sensor channel", "sensor channels"),
        "high_frequency_sampling": ("1 khz", "khz"),
        "vibration_or_signal": ("vibration", "signal"),
        "call_detail_records": ("cdr", "cdrs"),
        "market_data_or_positions": ("derivatives positions", "portfolio greeks", "monte carlo var"),
        "payment_authorization_events": ("card transaction", "card transactions", "payment transaction", "payment transactions", "authorization"),
    }
    result.telemetry_signals = _markers(lower, signal_markers)
    detection_markers = {
        "transformer_thermal_runaway": ("thermal runaway",),
        "feeder_prefault_oscillation": ("pre-fault oscillation", "prefault oscillation", "feeder line"),
        "historical_failure_patterns": ("historical failure pattern", "historical failure patterns"),
        "tool_failure_prediction": ("failure prediction", "predictive maintenance"),
        "catastrophic_failure_alerting": ("catastrophic alert", "catastrophic alerting"),
        "network_congestion_prediction": ("congestion", "prediction horizon"),
        "portfolio_risk_var": ("var", "portfolio greeks"),
        "payment_fraud_scoring": ("fraud", "risk score", "score events", "fraudulent transactions"),
    }
    result.detection_targets = _markers(lower, detection_markers)
    action_markers = {
        "dispatch_field_crews": ("dispatches field crews", "dispatch field crews", "field crew"),
        "preposition_replacement_equipment": ("pre-positions replacement equipment", "pre-position replacement equipment", "preposition replacement equipment"),
        "queue_suspicious_payments_for_analyst_review": ("queue suspicious payments", "analyst review", "review queue"),
        "block_high_confidence_fraud_after_policy_approval": ("block high-confidence", "block high confidence", "fraud after policy approval", "policy approval"),
    }
    result.operational_actions = _markers(lower, action_markers)
    payment_context = any(term in lower for term in ("card transaction", "payment fraud", "payment transaction", "authorization"))
    if any(term in lower for term in ("real-time", "realtime", "telemetry", "sensor", "iot")) and not payment_context and not re.search(r"\b\d+\s*(?:hz|khz|seconds?|minutes?)\b", lower):
        result.assumptions.append("Telemetry frequency was not provided; use a named assumption profile until confirmed.")
    if "payload" not in lower and "kb" not in lower and "mb" not in lower:
        if payment_context:
            result.assumptions.append("Transaction payload size was not provided; use a named fraud-pricing assumption profile until confirmed.")
        else:
            result.assumptions.append("Telemetry payload size was not provided; use a named assumption profile until confirmed.")
    return result


def _put_match(target: dict[str, MetricValue], key: str, unit: str, text: str, pattern: str) -> None:
    match = re.search(pattern, text, flags=re.I)
    if match:
        target[key] = MetricValue(_number(match.group("value")), unit, match.group(0).strip())


def _markers(lower: str, catalog: dict[str, tuple[str, ...]]) -> list[str]:
    return [name for name, markers in catalog.items() if any(marker in lower for marker in markers)]


def _number(value: str) -> float:
    return float(value.replace(",", ""))


_WORD_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
