# Pricing Filter Discovery

Return JSON only. Suggest AWS Price List API filter candidates for service recommendations.

Rules:
- Suggested filters are advisory evidence-discovery hints only.
- Do not output prices.
- Include confidence and rationale for each filter.
- Prefer explicit service names and region constraints from the deterministic profile.

