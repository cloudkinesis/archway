from app.services.golden_regression import GoldenRegressionExportService


def test_golden_regression_export_contains_distinct_matrix():
    export = GoldenRegressionExportService().export()

    assert export["scenario_count"] >= 10
    assert export["unique_capability_sets"] >= 10
    assert export["unique_service_sets"] >= 8
    assert any(row["name"] == "utility_grid" for row in export["rows"])
    assert all(row["compiler_views"] for row in export["rows"])
