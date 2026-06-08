from typing import Any

from app.services.pattern_catalog import expected_views, pricing_dimensions, service_recommendations, semantic_views
from app.services.use_case_profile import profile_use_case


class GoldenRegressionExportService:
    def export(self) -> dict[str, Any]:
        scenarios = _load_scenarios()
        rows = []
        for name, use_case in scenarios.items():
            profile = profile_use_case(use_case)
            services = service_recommendations(profile, evidence_ids=["golden_regression"])
            rows.append(
                {
                    "name": name,
                    "workload_families": profile.workload_families,
                    "capabilities": profile.capability_model,
                    "services": [item.service for item in services],
                    "pricing_dimensions": pricing_dimensions(profile),
                    "semantic_views": semantic_views(profile, production=True),
                    "compiler_views": expected_views(profile, production=True),
                    "hardcoding_guard": {
                        "rag_selected": "rag_assistant" in profile.workload_families,
                        "utility_grid_specific": name == "utility_grid",
                    },
                }
            )
        return {
            "scenario_count": len(rows),
            "unique_capability_sets": len({tuple(row["capabilities"]) for row in rows}),
            "unique_service_sets": len({tuple(row["services"]) for row in rows}),
            "rows": rows,
        }


def _load_scenarios() -> dict[str, str]:
    from tests.golden_scenarios.scenarios import GOLDEN_SCENARIOS, UTILITY_GRID

    return {"utility_grid": UTILITY_GRID, **GOLDEN_SCENARIOS}
