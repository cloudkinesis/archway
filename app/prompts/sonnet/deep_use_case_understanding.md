# Deep Use Case Understanding

Return JSON only. Extract the industry, domain, workload families, explicit metrics, latency targets, compliance constraints, and effectful action flows from the user-provided use case.

Rules:
- Do not invent missing metrics, prices, AWS facts, or compliance obligations.
- Preserve explicit user numbers and targets.
- Mark uncertainty in `critical_unknowns` or `concerns`.
- Treat deterministic extraction as a baseline, not as something to discard.

