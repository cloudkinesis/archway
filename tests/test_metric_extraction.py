from app.services.metric_extractor import extract_metrics
from app.services.use_case_profile import profile_use_case


def _profile_metric_map(text: str):
    return {metric.label: metric for metric in profile_use_case(text).metrics}


def test_refresh_cadence_extracts_every_minutes_and_minute_refresh():
    every_minutes = "The OR platform must refresh predictions every 2 minutes."
    minute_refresh = "The OR platform needs a 2-minute refresh for predictions."

    assert extract_metrics(every_minutes).business_targets["refresh_cadence_minutes"].value == 2
    assert extract_metrics(minute_refresh).business_targets["refresh_cadence_minutes"].value == 2
    assert _profile_metric_map(every_minutes)["refresh_cadence_minutes"].value == 2
    assert _profile_metric_map(minute_refresh)["refresh_cadence_minutes"].value == 2


def test_scheduled_surgeries_per_day_extraction_reaches_profile_metrics():
    use_case = "The hospital network handles 120 scheduled surgeries per day."

    structured = extract_metrics(use_case)
    profile_metrics = _profile_metric_map(use_case)

    assert structured.business_targets["scheduled_surgeries_per_day"].value == 120
    assert profile_metrics["scheduled_surgeries_per_day"].value == 120


def test_healthcare_profile_metrics_match_structured_metrics_for_pricing_drivers():
    use_case = "18 hospitals, 240 operating rooms, 120 scheduled surgeries per day, predictions every 2 minutes."

    structured = extract_metrics(use_case)
    profile_metrics = _profile_metric_map(use_case)

    expected = {
        "hospital_count": structured.asset_counts["hospital_count"].value,
        "operating_room_count": structured.asset_counts["operating_room_count"].value,
        "scheduled_surgeries_per_day": structured.business_targets["scheduled_surgeries_per_day"].value,
        "refresh_cadence_minutes": structured.business_targets["refresh_cadence_minutes"].value,
    }

    assert expected == {
        "hospital_count": 18,
        "operating_room_count": 240,
        "scheduled_surgeries_per_day": 120,
        "refresh_cadence_minutes": 2,
    }
    assert {key: profile_metrics[key].value for key in expected} == expected

