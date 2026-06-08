from pathlib import Path


def test_architecture_selection_modules_do_not_branch_on_industry_strings():
    root = Path(__file__).resolve().parents[2]
    checked = [
        root / "app/services/architecture.py",
        root / "app/services/pattern_catalog.py",
        root / "app/services/view_planner.py",
        root / "app/services/lane_planner.py",
        root / "app/services/pricing.py",
    ]
    banned = [
        'if industry == "telecom"',
        'if domain == "healthcare"',
        'if "utility" in use_case',
        'if use_case_type == "retail_banking"',
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in checked)

    assert not any(pattern in text for pattern in banned)

