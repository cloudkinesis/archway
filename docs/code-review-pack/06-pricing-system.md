# Pricing System

Pricing is one of Archway's highest-risk areas. The current system is designed to be honest about maturity instead of pretending all estimates are procurement-ready.

## Main Modules

- `app/services/pricing.py`: extracts pricing drivers and creates deterministic low/expected/high estimates.
- `app/services/pricing_driver_selector.py`: selects the pricing driver family.
- `app/services/pricing_driver_closure.py`: classifies drivers as confirmed, assumed, or missing and builds checkpoint questions.
- `app/services/pricing_scenario_profiles.py`: explicit scenario assumptions, currently strongest for live media.
- `app/services/source_truth_pricing_compiler.py`: builds canonical facts, assumptions, driver bindings, usage dimensions, ledger, sanity findings, and line-item annotations.
- `app/services/aws_price_list.py`: AWS Price List bulk index evidence and service matching.
- `app/services/aws_price_list_parser.py`: parses AWS Price List API-style responses.
- `app/services/aws_pricing_mcp.py`: optional AWS Labs Pricing MCP bridge.
- `app/services/aws_rate_binding_engine.py`: attempts to bind service usage to pricing rates.
- `app/services/pricing_filter_mapper.py`: maps service names to Price List filter plans.

## Pricing Readiness Ladder

Pricing should be understood as a ladder:

- `pricing_not_available`
- `pricing_placeholder_only`
- `pricing_directional_with_assumptions`
- `pricing_customer_demo_ready`
- `pricing_procurement_ready`

The code has metadata and UI concepts for maturity, closure, procurement readiness, and headline safety. Exact naming and enforcement should be reviewed because not all paths are equally mature.

## Procurement Ready Versus Demo Ready

Procurement-ready means:

- Workload drivers are confirmed or explicitly assumed.
- Usage quantities are traceable.
- Service usage dimensions are mapped.
- SKU/tier/rate binding is available where needed.
- Pricing ledger shows procurement readiness.

Customer-demo-ready can be lower maturity:

- Directional scenario estimate.
- Explicit assumptions.
- Caveats and validation steps.
- No exact-looking executive headline if unsafe.

## Headline Safety

The UI/export should not show exact-looking headline pricing when:

- Critical drivers are unresolved.
- Pricing trace/ledger is empty while costs are non-zero.
- SKU/rate binding is unavailable and line items are heuristic.
- Source truth compiler marks `headline_safe=false`.

In those cases pricing should be described as directional, assumption-backed, or withheld from the executive headline.

## Driver Families

Implemented or partially implemented families include:

- Healthcare operations scheduling.
- Live media streaming.
- Telecom CDR/network analytics.
- Payment fraud.
- Investment risk simulation.
- Other generic/directional fallback paths.

Healthcare OR prediction must use active ORs, refresh cadence, operating window, surgery/event rates, approval/EHR writeback and audit drivers. It must not use IoT `asset_count * telemetry_frequency` style scale.

Media streaming must use viewer-hours, bitrate, CDN egress, channel-hours, ad/DRM/QoE/log/archive drivers.

Telecom must preserve CDR/tower/retention/prediction/QoS scale where present.

## MCP and Price List Boundary

The official AWS Pricing MCP can provide structured pricing data when configured. The managed AWS Docs MCP should be treated as documentation/evidence, not a substitute for procurement-grade pricing queries.

Settings support:

- AWS Pricing MCP URL/auth.
- AWS Pricing MCP command/args/profile/region.
- AWS Docs MCP URL/auth.
- AWS Price List bulk index fallback/reference.

No credentials should be embedded in docs or code.

## Known Pricing Gaps

- Some line items can still be heuristic.
- Some workload families have better driver closure than others.
- Scenario profiles are not available for every domain.
- Rate binding can fail or be unavailable for services/tiers.
- Non-zero cost with weak ledger data must remain a warning/blocker.
- Procurement readiness is a higher bar than customer demo readiness.

Reviewers should inspect both metadata and rendered UI/export wording, because an honest backend trace can still be weakened by misleading presentation.

