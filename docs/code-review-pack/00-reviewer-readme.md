# Archway Code Review Pack

This pack is for an external LLM or human reviewer who needs to understand the current Archway codebase without reading every file first. It is documentation-only. It does not introduce new behavior, refactor code, or run expensive scenarios.

Archway is an AWS solution architecture assistant. It takes a use case, conducts an interview, researches AWS direction and market context, plans POC and production architecture, compiles diagrams through the existing D2 compiler integration, validates governance and pricing readiness, and exports a dossier zip.

## Review Priorities

Review these areas first because they carry the highest product risk:

1. Security and tool governance: effectful actions, approval controls, external writes, safe defaults, and auditability.
2. Evidence and citation discipline: whether the UI and export distinguish facts, recommendations, assumptions, and uncertain claims.
3. Pricing accuracy and honesty: whether workload-specific drivers, SKU/rate backing, assumptions, and headline-safe rules are applied correctly.
4. D2 compiler boundary: Archway should use the configured compiler adapter and must not replace the compiler with an internal shortcut.
5. Domain drift: healthcare, telecom, media, generic app, and other domains must not leak language, pricing drivers, or diagram views into each other.

## Suggested Reading Order

Read:

1. `01-system-architecture.md`
2. `04-data-models-and-artifacts.md`
3. `05-domain-pack-and-classification-system.md`
4. `06-pricing-system.md`
5. `07-diagram-compiler-integration.md`
6. `08-repair-and-convergence.md`
7. `10-known-gaps-and-review-questions.md`

Use the module maps when you need file-level navigation.

## Important Truths

The system is not fully procurement-ready. It has meaningful pricing plumbing, workload driver families, source truth ledger concepts, AWS Price List parsing, and MCP integration hooks, but many estimates remain directional unless the needed usage drivers and SKU/rate bindings are present.

The frontend has improved research presentation, session hydration, diagram inspection, and chat composer behavior, but it remains largely concentrated in one large React component file. That is a maintainability risk, not necessarily a functional blocker.

The repair/convergence loop exists and records repairs, but it is still a bounded, deterministic repair system. It is not a universal autonomous architecture fixer.

## No Secrets

This documentation intentionally excludes API keys, real credentials, raw session artifacts, private customer data, and local environment values that may contain secrets.

