# Review Prompts

Use these prompts with another LLM after pasting the relevant docs and code snippets.

## Whole-System Review

Review Archway as an AWS solution architecture assistant. Prioritize security/tool governance, evidence discipline, pricing honesty, domain drift, and D2 compiler boundary. Identify correctness bugs, trust risks, and missing tests. Do not focus on cosmetic UI unless it affects trust or usability.

## Pricing Review

Review the pricing system. Check whether workload-specific drivers are selected correctly, whether fallback/heuristic pricing is labeled honestly, whether non-zero estimates with weak ledger data are blocked or warned, and whether procurement-ready is distinguished from customer-demo-ready. Point to exact code paths that could mislead users.

## Domain Drift Review

Review classification, synthesis, pricing, research presentation, pattern catalog, and dossier code for domain leakage. Use generic web app, telecom HBase/HDFS migration, media streaming analytics, and healthcare OR scheduling as anti-drift scenarios. Identify where healthcare, telecom, media, or IoT wording can leak across domains.

## Governance Review

Review effectful flow governance. Confirm create/update/delete/dispatch/pre-position/external-write/policy-change/trade-block/device-update/network-change flows receive typed controls with governed flow ids. Check that unresolved unsafe actions become recommendation-only or queue-for-review instead of silently passing.

## Diagram Compiler Review

Review diagram integration. Confirm Archway uses the configured D2 compiler adapter, tracks semantic requested views, reports dropped views, and does not hide compiler QA failures. Check icon embedding metrics separately from actual layout/placement/crossing issues.

## Evidence/Citation Review

Review evidence discipline. Confirm facts, recommendations, assumptions, uncertainties, AWS docs, pricing evidence, user input, local policy, and web/Tavily results are labeled distinctly. Check that raw evidence ids are not shown in default UI and that claims in export have traceable evidence or explicit uncertainty.

## Frontend Trust UX Review

Review the React app for trust UX. Confirm completed session hydration restores all tabs, research default view is readable, buttons are wired or clearly disabled, chat composer remains visible, diagram inspector is usable, and progress labels update meaningfully.

## Test Coverage Review

Review tests and identify missing high-value tests. Prioritize focused deterministic tests over flaky browser automation unless UI behavior cannot be validated otherwise. Look for gaps in pricing readiness, domain anti-drift, governance controls, diagram semantic views, hydration, and export package integrity.

