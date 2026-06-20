# Archway System and AWS Demo Deployment Handoff

Status: current as of `master` commit `515ced4b6f1b2367aa1a486608915a941bad241d`
Audience: deployment engineer, AWS operator, or external system taking over demo hosting
Scope: demo-grade AWS deployment with strong performance and sane security, not a fully multi-tenant production architecture

## 1. What Archway Is

Archway is an AWS solution architecture assistant. A user enters a rough use case, answers interview questions, and then Archway produces:

- a structured use-case brief,
- research and evidence notes,
- AWS service recommendations,
- directional or authority-backed pricing analysis,
- POC and production architecture specifications,
- rendered architecture diagrams,
- executive/client-facing dossier files,
- raw audit/evidence/pricing/LLM trace files,
- a downloadable ZIP package.

The important product principle is: Archway should complete the user journey, but it must not pretend that directional pricing is procurement-ready. Exact procurement-ready pricing requires authoritative rate binding and confirmed quantities. If those are missing, the package should remain workshop-ready or directional and explain why.

## 2. Recommended Demo Deployment Shape

For the next AWS-hosted demo, use the simplest reliable shape:

```text
Browser
  -> HTTPS
  -> Nginx on one EC2 instance
       /          serves frontend/dist static files
       /api/*     reverse proxies to FastAPI on 127.0.0.1:8000
  -> systemd service running uvicorn app.main:app
  -> local EBS volume for ARCHWAY_DATA_DIR
  -> Bedrock, Tavily, AWS Docs/Pricing MCP, AWS Price List APIs as outbound calls
```

This is intentionally not an elaborate production architecture. It is the best fit for a live stakeholder demo because it avoids cold-starts, avoids distributed state, keeps ZIP generation local and fast, and lets the whole app share one persistent artifact directory.

Recommended EC2 class for a smooth demo:

- `m7i.large`, `m7i.xlarge`, `c7i.large`, or similar.
- Minimum: 2 vCPU / 8 GiB RAM.
- Better demo comfort: 4 vCPU / 16 GiB RAM if several people will run sessions.
- EBS: at least 50 GiB gp3, more if keeping many generated ZIPs and diagrams.

Use a private security posture where possible:

- Inbound: `443` from approved user IPs; optionally `22` from admin IP only.
- Do not expose backend port `8000` publicly.
- Backend should listen on `127.0.0.1:8000`.
- Nginx terminates TLS and proxies `/api`.
- Store secrets in AWS Systems Manager Parameter Store or Secrets Manager, not in Git.

## 3. Repository Layout

Important files and directories:

```text
app/main.py
  FastAPI module-level app instance. Adds CORS, security headers, request limit, rate limit, safe error handler, and API router.

app/api/routes.py
  Main API controller. Owns session creation, synthesis, research jobs, pricing checkpoint, architecture jobs,
  diagram jobs, diagnostics, artifact serving, and export package generation.

app/core/config.py
  Environment-driven settings. This is the canonical list for runtime flags, model IDs, keys, data path,
  MCP endpoints, Bedrock, Tavily, AWS pricing, and compiler timeout/concurrency.

app/security/policy.py
  API middleware for security headers, max request size, and simple in-memory rate limiting.

app/db/session_store.py
  SQLite session index. Stores serialized Session payloads in ARCHWAY_DATA_DIR/archway.sqlite3.

app/services/artifacts.py
  Safe filesystem artifact store. Session files live under ARCHWAY_DATA_DIR/sessions/<session_id>.
  Prevents absolute-path and ../ artifact traversal.

app/services/synthesis.py
  Initial use-case brief, interview question generation, readiness checks, assumptions, and answer recording.

app/services/use_case_profile.py
app/services/capability_extractor.py
app/services/open_world_understanding.py
app/services/understanding/
  Deterministic and optional live Bedrock use-case understanding. The current system uses a deterministic
  evidence backbone plus optional LLM understanding/judge verification.

app/services/research.py
  Research orchestration. Runs understanding, AWS Docs evidence, Tavily competitor scan if enabled,
  service selection, pricing estimate, AWS Price List evidence, pricing sanity review, source/citation gates,
  and readiness metadata.

app/services/tavily.py
  Tavily web search client. Disabled unless ARCHWAY_ENABLE_WEB_SEARCH=true and a key/budget are configured.

app/services/aws_research_tools.py
app/services/mcp_http.py
app/services/mcp_stdio.py
app/services/mcp_security.py
  AWS Docs/Pricing MCP integration and endpoint security controls.

app/services/pricing.py
app/services/source_truth_pricing_compiler.py
app/services/pricing_authority_resolver.py
app/services/aws_rate_binding_engine.py
app/services/aws_price_list.py
app/services/aws_price_list_query.py
app/services/aws_price_list_parser.py
  Pricing stack. Produces directional estimates, canonical facts, usage dimensions, rate bindings,
  pricing ledger, and fail-closed procurement readiness decisions.

app/services/canonical_intent.py
app/services/architecture.py
app/services/architecture_critique.py
app/services/governance_controls.py
app/services/convergence/architecture_repairer.py
  Architecture selection, canonical intent gates, judge/critique integration, governance enrichment,
  and deterministic repairs.

app/services/diagram_compiler_adapter.py
packages/archway_diagram_compiler/
  In-repo diagram compiler adapter and vendored compiler source. The Python compiler code is vendored,
  but SVG rendering still requires a d2 executable available on PATH or at .tools/d2/d2.

app/services/export_package.py
app/services/client_pack.py
app/services/deep_dossier.py
app/services/dossier_manifest.py
app/services/convergence/golden_convergence_orchestrator.py
  ZIP/package generation, client/audit pack files, dossier narrative, manifest, and quality/readiness summary.

app/services/jobs.py
  In-memory background job manager. Research, architecture, diagrams, and export run as polled jobs.

app/services/health.py
app/services/build_status.py
  Health and build readiness endpoints.

frontend/
  Vite React application.

frontend/src/lib/api.ts
  Typed fetch wrapper. VITE_ARCHWAY_API_BASE controls the API base URL. Includes endpoint-specific timeouts.

frontend/src/components/App.tsx
frontend/src/components/synthesis/SynthesisTab.tsx
frontend/src/components/architecture/ArchitectureViewer.tsx
frontend/src/components/TrustPanel.tsx
  Main UI shell and major user-facing panels.

scripts/rc2_validate.py
scripts/rc2_golden_export_validation.py
scripts/d25_convergence_eval_battery.py
scripts/d21_eval_battery.py
scripts/d21_demo_readiness_check.py
scripts/d23_eval_battery.py
  Validation harnesses and quality gates.

tests/
  Backend unit, integration, anti-drift, pricing, export, diagram, D21-D38, and golden regression tests.

docs/code-review-pack/
  Existing detailed reviewer maps. This handoff is the deployment/operator document; the review pack remains useful for deeper code review.
```

## 4. Runtime Workflow

The browser-driven workflow maps to these backend phases:

1. **Create session**
   - UI calls `POST /api/sessions`.
   - Route: `app/api/routes.py:create_session`.
   - Engine: `app/services/synthesis.py`.
   - Writes `brief/current.json`.
   - Session row is created in SQLite.

2. **Interview / synthesis**
   - UI calls `POST /api/sessions/{id}/synthesis/message` for answers.
   - UI calls `POST /api/sessions/{id}/synthesis/proceed`.
   - Archway usually asks up to four important questions. If the user proceeds early, assumptions are recorded.

3. **Research**
   - UI calls `POST /api/sessions/{id}/research/run`.
   - A background job is created in `app/services/jobs.py`.
   - UI polls `GET /api/sessions/{id}/jobs/{job_id}` and hydrates data.
   - `ResearchOrchestrator` runs:
     - local policy evidence,
     - use-case profile and deep understanding,
     - optional Bedrock open-world understanding,
     - optional AWS Docs MCP search,
     - optional Tavily competitor scan,
     - service recommendations,
     - pricing estimate,
     - AWS Price List bulk/query/MCP evidence where configured,
     - pricing sanity review,
     - customer readiness metadata.
   - Writes `research/report.json` and `pricing/estimate.json`.

4. **Pricing checkpoint**
   - UI may call pricing checkpoint endpoints if drivers are missing.
   - This can answer driver values, use scenario profiles, or proceed without headline pricing.
   - Procurement-ready pricing is withheld unless quantities and authoritative rates are bound.

5. **Architecture**
   - UI calls `POST /api/sessions/{id}/architecture/generate`.
   - Background job runs:
     - `ArchitecturePlanner`,
     - `GovernanceControlEnricher`,
     - `ArchitectureCritiqueService`,
     - `ArchitectureRepairer`.
   - Current D38 behavior uses canonical intent gates to prevent borrowed telemetry/streaming topology when the evidence does not support it.
   - Writes architecture specs and revision metadata.

6. **Diagrams**
   - UI calls `POST /api/sessions/{id}/diagrams/generate`.
   - `DiagramCompilerAdapter` converts architecture specs to compiler semantic specs.
   - The vendored compiler renders D2/SVG artifacts via a `d2` executable.
   - Writes `diagrams/gallery.json` and diagram files under the session folder.

7. **Export**
   - UI calls `POST /api/sessions/{id}/export/generate`.
   - `ExportPackageService` builds client-facing markdown, audit/raw JSON, diagram downloads, quality/readiness summaries, manifest, and ZIP.
   - UI calls `GET /api/sessions/{id}/export/package`.
   - ZIPs live under `ARCHWAY_DATA_DIR/sessions/<session_id>/exports/`.

## 5. Persistence and Backup

The deployment must preserve `ARCHWAY_DATA_DIR`.

Default local path:

```text
.archway/
```

Recommended AWS path:

```text
/var/lib/archway
```

Contents:

```text
/var/lib/archway/archway.sqlite3
/var/lib/archway/logs/
/var/lib/archway/sessions/<session_id>/
  brief/
  research/
  pricing/
  architecture/
  diagrams/
  exports/
  raw/
```

For demo hosting, this can be a local EBS-backed filesystem. Snapshot the EBS volume before major changes. If this becomes multi-user or production, migrate sessions/artifacts to managed storage deliberately; do not bolt that onto this demo deployment without test coverage.

## 6. Secrets and Configuration

Never commit secrets to Git. Do not bake secrets into AMIs. Prefer one of these:

1. **AWS Systems Manager Parameter Store** secure strings, loaded into the systemd environment at boot/deploy time.
2. **AWS Secrets Manager**, loaded into the systemd environment at boot/deploy time.
3. For a short-lived private demo only: a root-owned env file at `/etc/archway/archway.env` with mode `0600`.

Recommended root-owned env file:

```bash
sudo install -d -m 0750 -o root -g root /etc/archway
sudo touch /etc/archway/archway.env
sudo chown root:root /etc/archway/archway.env
sudo chmod 0600 /etc/archway/archway.env
```

Minimum useful demo configuration:

```bash
ARCHWAY_ENV=production
ARCHWAY_DATA_DIR=/var/lib/archway
ARCHWAY_CORS_ORIGINS=https://YOUR_DEMO_DOMAIN

ARCHWAY_LLM_PROVIDER=bedrock
ARCHWAY_AGENTIC_MODE=live_demo
ARCHWAY_ENABLE_OPEN_WORLD_UNDERSTANDING=true
ARCHWAY_DISABLE_DOMAIN_REFINERS=true

ARCHWAY_BEDROCK_REGION=us-east-1
ARCHWAY_BEDROCK_MAIN_MODEL_ID=us.amazon.nova-pro-v1:0

ARCHWAY_ENABLE_LLM_JUDGE=true
ARCHWAY_BEDROCK_JUDGE_MODEL_ID=us.amazon.nova-2-lite-v1:0

ARCHWAY_BEDROCK_MAX_TOKENS=8192
ARCHWAY_BEDROCK_TIMEOUT_SECONDS=120
ARCHWAY_BEDROCK_RETRY_COUNT=2
ARCHWAY_AGENTIC_MAX_BEDROCK_CALLS=12
ARCHWAY_AGENTIC_SCHEMA_REPAIR_RETRIES=1

ARCHWAY_ENABLE_WEB_SEARCH=true
ARCHWAY_ENABLE_COMPETITOR_WEB_SEARCH=true
ARCHWAY_TAVILY_API_KEY=REPLACE_WITH_SECRET
ARCHWAY_TAVILY_MAX_CALLS_PER_SESSION=2

ARCHWAY_ENABLE_AWS_DOCS_MCP=true
ARCHWAY_AWS_DOCS_MCP_URL=REPLACE_IF_AVAILABLE
ARCHWAY_AWS_DOCS_MCP_AUTH_TOKEN=REPLACE_IF_REQUIRED

ARCHWAY_ENABLE_AWS_PRICING_MCP=true
ARCHWAY_AWS_PRICING_MCP_COMMAND=REPLACE_IF_USING_STDIO_MCP
ARCHWAY_AWS_PRICING_MCP_ARGS=REPLACE_IF_USING_STDIO_MCP

ARCHWAY_ENABLE_AWS_PRICE_LIST_QUERY_API=false
ARCHWAY_ENABLE_AWS_OFFICIAL_WEB_FALLBACK=false

ARCHWAY_COMPILER_TOTAL_TIMEOUT_SECONDS=120
ARCHWAY_COMPILER_MAX_CONCURRENT_JOBS=1
```

Notes:

- `ARCHWAY_BEDROCK_MAIN_MODEL_ID` should usually use the inference-profile form, for example `us.amazon.nova-pro-v1:0`, because many AWS accounts cannot invoke Nova Pro through the bare on-demand model ID.
- Use the bare model ID, for example `amazon.nova-pro-v1:0`, only if on-demand invocation for that model is enabled in the target AWS account and region.
- The judge only runs when `ARCHWAY_ENABLE_LLM_JUDGE=true` and a judge model or inference profile is configured.
- Use `ARCHWAY_BEDROCK_JUDGE_INFERENCE_PROFILE_ID` instead of `ARCHWAY_BEDROCK_JUDGE_MODEL_ID` if the judge model is exposed through an inference profile.
- Tavily health intentionally avoids live probes when budget is zero to preserve quota.
- `ARCHWAY_ENABLE_AWS_PRICE_LIST_QUERY_API` defaults to false. Turning it on makes live boto3 Price List Query API calls. Leave it false for reproducible demo behavior unless specifically validating live pricing authority.
- MCP tokens are only sent to trusted endpoints. External MCP hosts require `ARCHWAY_MCP_ALLOWED_HOSTS` or `ARCHWAY_MCP_ALLOW_EXTERNAL=true`. Prefer allowlisting exact hosts.

## 7. AWS IAM Requirements

Attach an IAM role to the EC2 instance. Avoid static AWS access keys on disk.

Minimum permissions depend on which live integrations you enable:

- Bedrock runtime:
  - `bedrock:InvokeModel`
  - `bedrock:InvokeModelWithResponseStream` if streaming is later used
  - access to the configured model/inference profile in the selected region
- AWS Price List Query API if enabled:
  - `pricing:GetProducts`
  - `pricing:DescribeServices`
  - `pricing:GetAttributeValues`
- SSM/Secrets Manager if loading secrets at boot:
  - `ssm:GetParameter` / `ssm:GetParameters`
  - or `secretsmanager:GetSecretValue`
- CloudWatch Logs if systemd logs are shipped:
  - permissions required by the log agent, if installed

For a demo, keep permissions narrow. The app does not need to create AWS infrastructure.

## 8. Install on a Fresh EC2 Host

Use an image with Python 3.11+ and Node.js 20+. Vite 6 should not be deployed with an old distro Node.js package.

Example for Amazon Linux 2023:

```bash
sudo dnf update -y
sudo dnf install -y git nginx python3.11 python3.11-pip nodejs npm unzip curl rsync
node --version
python3.11 --version
```

If the Amazon Linux package gives Node.js below 20, install Node.js 20 from your approved package source before running `npm ci`.

Example for Ubuntu 24.04:

1. Install OS packages:

```bash
sudo apt-get update
sudo apt-get install -y git nginx python3.12 python3.12-venv python3-pip nodejs npm unzip curl rsync
node --version
python3.12 --version
```

If the Ubuntu package gives Node.js below 20, install Node.js 20 from your approved package source before running `npm ci`.

2. Install D2:

```bash
curl -fsSL https://d2lang.com/install.sh | sh -s --
sudo install -m 0755 "$HOME/.local/bin/d2" /usr/local/bin/d2
d2 --version
```

If this install path is not acceptable, place a `d2` binary at repo path `.tools/d2/d2` or ensure `d2` is on the service PATH. Diagram rendering will fail without it.

3. Create application user and directories:

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin archway || true
sudo install -d -m 0750 -o archway -g archway /opt/archway
sudo install -d -m 0750 -o archway -g archway /var/lib/archway
sudo install -d -m 0750 -o root -g root /etc/archway
```

4. Clone the repo:

```bash
sudo -u archway git clone https://github.com/cloudkinesis/archway.git /opt/archway/app
cd /opt/archway/app
git rev-parse HEAD
```

5. Python environment:

```bash
cd /opt/archway/app
sudo -u archway python3.11 -m venv .venv
sudo -u archway .venv/bin/pip install --upgrade pip
sudo -u archway .venv/bin/pip install -r requirements.txt
```

On Ubuntu 24.04, replace `python3.11` with `python3.12` in the venv command.

6. Frontend dependencies and build:

```bash
cd /opt/archway/app/frontend
sudo -u archway npm ci
sudo -u archway npm run build
```

For same-origin Nginx proxy, no `VITE_ARCHWAY_API_BASE` is needed. If serving frontend and API on different hosts, build with:

```bash
VITE_ARCHWAY_API_BASE=https://YOUR_API_HOST/api npm run build
```

7. Write `/etc/archway/archway.env` using the environment variables in section 6.

8. Install systemd first, then verify backend through systemd. This keeps secret loading identical to the real service path and avoids ad-hoc shell parsing of `/etc/archway/archway.env`.

After creating the service in the next section, verify:

```bash
curl -s http://127.0.0.1:8000/api/health
curl -s http://127.0.0.1:8000/api/build/status
```

## 9. systemd Backend Service

Create `/etc/systemd/system/archway.service`:

```ini
[Unit]
Description=Archway FastAPI backend
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=archway
Group=archway
WorkingDirectory=/opt/archway/app
EnvironmentFile=/etc/archway/archway.env
Environment=PATH=/opt/archway/app/.venv/bin:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=/opt/archway/app/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
Restart=on-failure
RestartSec=5
TimeoutStopSec=30

# Demo hardening. Keep writable paths limited to app/data/tmp needs.
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=/var/lib/archway /opt/archway/app/.archway

[Install]
WantedBy=multi-user.target
```

Why one worker? The current job manager is in-memory. Multiple backend workers would split job state and confuse polling. For this demo deployment, use one uvicorn process and scale vertically with a larger EC2 instance. If production scaling is needed later, move job state to a shared queue/store first.

Start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now archway
sudo systemctl status archway
journalctl -u archway -f
```

## 10. Nginx Frontend and Reverse Proxy

Copy frontend build output:

```bash
sudo install -d -m 0755 /var/www/archway
sudo rsync -a --delete /opt/archway/app/frontend/dist/ /var/www/archway/
```

Example Nginx site:

```nginx
server {
    listen 80;
    server_name YOUR_DEMO_DOMAIN;

    client_max_body_size 1m;

    root /var/www/archway;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 30s;
        proxy_send_timeout 180s;
        proxy_read_timeout 180s;
    }

    location / {
        try_files $uri /index.html;
    }
}
```

The Nginx body limit is intentionally higher than the backend request limit. The backend still rejects request bodies above `64_000` bytes with HTTP 413 through `RequestLimitMiddleware`; this protects the app even if Nginx is configured more generously.

Enable TLS before external stakeholder use. Use your normal certificate flow or Certbot. After TLS, set:

```bash
ARCHWAY_CORS_ORIGINS=https://YOUR_DEMO_DOMAIN
```

Restart:

```bash
sudo nginx -t
sudo systemctl reload nginx
sudo systemctl restart archway
```

## 11. Performance Notes for the Demo

The slowest operations are Bedrock calls, research, diagram rendering, and export generation. For best demo performance:

- Run on EC2 in the same region as Bedrock (`ARCHWAY_BEDROCK_REGION`, currently usually `us-east-1`).
- Use one backend worker because jobs are in-memory.
- Use a larger instance instead of multiple workers.
- Keep `ARCHWAY_COMPILER_MAX_CONCURRENT_JOBS=1` unless you have tested concurrent diagram rendering on the host.
- Keep `ARCHWAY_BEDROCK_TIMEOUT_SECONDS=120`.
- Keep Nginx `proxy_read_timeout` at least `180s`.
- Use frontend static files from Nginx, not Vite dev server.
- Keep `/var/lib/archway` on gp3 EBS.
- Do not run the full pytest suite on the demo host during stakeholder sessions.

## 12. Security Notes

Current in-code protections:

- Security headers are set in `app/security/policy.py`.
- Request body limit defaults to `64_000` bytes.
- Simple in-memory per-client rate limiting is enabled.
- Artifact serving is path-safe through `ArtifactStore.resolve`.
- MCP endpoint trust controls fail closed for unsafe external hosts unless allowlisted.
- Health/diagnostic APIs do not return raw secrets.

Deployment responsibilities:

- Put the site behind HTTPS.
- Restrict inbound access to approved IPs for a private beta/demo.
- Use an EC2 instance profile instead of static AWS keys.
- Store Tavily/MCP tokens in SSM Parameter Store, Secrets Manager, or `/etc/archway/archway.env` with `0600`.
- Do not commit `.env`.
- Do not expose `/var/lib/archway` over Nginx.
- Do not expose `:8000` publicly.
- Rotate Tavily and MCP tokens after broad demos.

Known demo limitation:

- This is not a multi-tenant authenticated SaaS yet. If sharing with beta clients, place it behind VPN, an ALB with authentication, CloudFront access controls, or another temporary access gate. Do not present the current demo deployment as production-grade multi-user hosting.

## 13. Health Checks After Deployment

Run:

```bash
curl -s https://YOUR_DEMO_DOMAIN/api/health
curl -s https://YOUR_DEMO_DOMAIN/api/build/status
```

Expected:

- `backend`: ready
- `database`: ready
- `artifact_dir`: ready
- `log_dir`: ready
- `diagram_compiler`: ready
- `open_world_live_mode`: ready when live demo flags and Bedrock config are active
- `bedrock_sonnet`: ready when Bedrock model access works. This is a legacy health-check key name; it checks the configured main Bedrock model, not necessarily Claude Sonnet.
- Tavily/AWS Docs/Pricing may show degraded if intentionally disabled or budgeted to zero

Use:

```bash
curl -s -X POST https://YOUR_DEMO_DOMAIN/api/health/retry
```

when changing external provider config; regular health checks cache remote checks briefly.

## 14. Browser Smoke Test

Use a brand-new scenario, not a known golden fixture.

1. Open `https://YOUR_DEMO_DOMAIN`.
2. Confirm the health gate is usable and does not show required failures.
3. Create a new session with a fresh use case.
4. Answer four interview questions.
5. Proceed to research.
6. Wait for research completion.
7. Review research summary, evidence, competitor section, pricing status, and assumptions.
8. Generate architecture.
9. Confirm POC and production architecture are readable and use the right topology for the use case.
10. Generate diagrams.
11. Open at least one diagram in the inspector.
12. Generate export.
13. Download the ZIP.
14. Inspect:
    - `README.md`
    - `02A-executive-summary.md`
    - `03-pricing.md`
    - `04-architecture.md`
    - `05-diagrams.md`
    - `raw/golden_convergence_result.json`
    - `raw/customer_readiness.json`
    - `raw/aws_rate_bindings.json`
    - `raw/llm_call_telemetry.json`
    - `manifest.json`

The desired demo outcome is usually `workshop_ready`. Do not force `procurement_ready`; that should happen only when exact pricing quantities and authoritative rate bindings are confirmed.

## 15. Test Commands

Run from repository root.

Fast confidence before deployment:

```bash
.venv/bin/python -m pytest tests/test_health.py tests/test_bedrock_plumbing.py tests/test_d38_canonical_intent_spine.py -q
cd frontend && npm run build
```

Full application suite:

```bash
.venv/bin/python -m pytest -q
```

Golden validation:

```bash
.venv/bin/python scripts/rc2_validate.py --profile golden --frontend --allow-missing-optional-tests
```

Expected current result:

```text
READY
passed=789
known_fail=0
new_fail=0
skipped=0
```

Golden package verifier:

```bash
.venv/bin/python scripts/rc2_golden_export_validation.py
```

Open-world / convergence quality checks:

```bash
.venv/bin/python scripts/d25_convergence_eval_battery.py
.venv/bin/python scripts/d21_demo_readiness_check.py
```

Frontend build:

```bash
cd frontend
npm run build
```

Optional live Bedrock eval:

```bash
ARCHWAY_ENABLE_OPEN_WORLD_UNDERSTANDING=true \
ARCHWAY_DISABLE_DOMAIN_REFINERS=true \
ARCHWAY_AGENTIC_MODE=live_demo \
ARCHWAY_LLM_PROVIDER=bedrock \
.venv/bin/python scripts/d23_eval_battery.py --live
```

Only run live eval when Bedrock credentials/model access and quota are available.

## 16. Deployment Update Procedure

For a docs/code update:

```bash
cd /opt/archway/app
sudo -u archway git fetch origin
sudo -u archway git checkout master
sudo -u archway git pull --ff-only origin master
sudo -u archway .venv/bin/pip install -r requirements.txt
cd frontend
sudo -u archway npm ci
sudo -u archway npm run build
sudo rsync -a --delete dist/ /var/www/archway/
sudo systemctl restart archway
sudo nginx -t
sudo systemctl reload nginx
```

Then run:

```bash
curl -s https://YOUR_DEMO_DOMAIN/api/health
curl -s https://YOUR_DEMO_DOMAIN/api/build/status
```

## 17. Troubleshooting

### Health says Bedrock is degraded

Check:

- EC2 IAM role has Bedrock permissions.
- The model or inference profile exists in `ARCHWAY_BEDROCK_REGION`.
- `ARCHWAY_BEDROCK_MAIN_MODEL_ID` is configured.
- For judge: `ARCHWAY_ENABLE_LLM_JUDGE=true` and judge model/profile is configured.
- Region/model access has been granted in the AWS account.

### Diagrams fail or no diagram cards appear

Check:

- `d2 --version` works for the `archway` user.
- `diagram_compiler` health check is ready.
- `ARCHWAY_COMPILER_TOTAL_TIMEOUT_SECONDS` is high enough.
- Nginx and frontend can fetch `/api/sessions/<id>/artifacts/<artifact_id>`.
- Session folder under `ARCHWAY_DATA_DIR` is writable.

### Research takes too long

Check:

- Bedrock timeout and Nginx proxy timeout.
- Tavily budget and external network access.
- AWS Docs/Pricing MCP endpoint latency.
- `journalctl -u archway -f` for job exceptions.

### Export ZIP does not appear

Check:

- Job status endpoint for export job failure.
- `/var/lib/archway` free disk space and permissions.
- `raw/golden_convergence_result.json` generation errors in logs.
- Nginx proxy timeout if the export request/poll appears stuck.

### Pricing is not procurement-ready

This is often correct. Inspect:

- `raw/aws_rate_bindings.json`
- `raw/pricing_driver_bindings.json`
- `raw/pricing_ledger.json`
- `03-pricing.md`

If rates are unbound or quantities are assumed, Archway should withhold procurement-ready claims.

## 18. What Not To Change Casually

Do not casually change these without tests:

- `app/core/config.py` default flags.
- `app/services/source_truth_pricing_compiler.py` procurement readiness and pricing ledger behavior.
- `app/services/pricing_authority_resolver.py` fail-closed rate-binding behavior.
- `app/services/canonical_intent.py` evidence gates without anti-drift tests.
- `app/services/architecture.py` topology selection/gating.
- `app/services/export_package.py` required root files and raw/audit artifacts.
- `app/services/dossier_manifest.py` manifest requirements.
- `app/services/diagram_compiler_adapter.py` compiler boundary.
- `app/security/policy.py` request/artifact/security controls.

Any change in those areas should run full pytest, frontend build, and RC2 golden validation.

## 19. Current Confidence and Honest Limits

Current validated state before this handoff:

- `master` pushed to GitHub at `515ced4b6f1b2367aa1a486608915a941bad241d`.
- Full pytest passed: `789 passed`.
- Frontend build passed.
- RC2 golden validation passed: `READY`, `known_fail=0`, `new_fail=0`.
- Fresh D38 live package reached `workshop_ready` with correct document/workflow topology and no telemetry leakage.

Honest limits:

- This is a demo/workshop assistant, not a production SaaS.
- It has no first-party login/multi-tenant access model yet.
- It uses local SQLite and local artifact storage.
- Job state is in-memory, so use one backend worker.
- Procurement-ready pricing requires authoritative rates and confirmed quantities; many arbitrary use cases will be workshop-ready or directional until pricing evidence is complete.
- AWS deployment should be treated as private beta/demo unless an authentication and tenancy layer is added.

## 20. Quick Operator Checklist

Before a stakeholder demo:

- `git rev-parse HEAD` matches expected commit.
- `systemctl status archway` is healthy.
- `curl /api/health` has no required failures.
- `curl /api/build/status` is acceptable.
- `d2 --version` works.
- Bedrock health is ready.
- Judge health/config is visible in `/api/health`.
- Tavily is either ready or intentionally disabled with budget notes.
- AWS Docs/Pricing MCP status is understood.
- Create one fresh session and complete research -> architecture -> diagrams -> export.
- Download and open the ZIP.
- Confirm package readiness is honest (`workshop_ready` is acceptable; fake procurement-ready is not).
