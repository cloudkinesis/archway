# Official AWS Price List offer slices (test fixtures)

These are **small REAL-shape slices** trimmed from the actual official AWS Price List
service offer files for **us-east-1** (validated 2026-06). Each keeps only the handful
of products/terms a test needs (plus a few real decoys), with `appliesTo` arrays stripped
for size. The rate values are real, public AWS data.

They are **NOT** the full official offer files (which are large and must not be committed),
and a slice is **NOT** an authoritative production snapshot. Refresh from the live AWS
Price List bulk API before any procurement use.

Files use the **real AWS offer codes**:
- `AmazonS3.json`, `AWSLambda.json`, `AmazonDynamoDB.json`, `AmazonCloudWatch.json`
- `AWSQueueService.json` — Amazon **SQS**
- `AWSEvents.json` — Amazon **EventBridge** (intentionally **unsupported** by the builder:
  AWS bills custom events per `64K-Chunks`, which does not match the pilot's per-`Events`
  model without an unverified ≤64KB assumption — fail closed)
- `AWSLambda_second_unit.json` — **SYNTHETIC** (not real): models a Lambda duration priced
  in unit `Second` to exercise alias normalization + the GB-second proof gate.
