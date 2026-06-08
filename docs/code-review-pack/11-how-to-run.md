# How to Run

These commands assume the repository root is `/Users/arnab/Documents/Archway` and dependencies are already installed.

## Backend

Run FastAPI:

```bash
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Health:

```bash
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/build/status
```

## Frontend

Run Vite:

```bash
cd frontend
npm run dev -- --host 127.0.0.1
```

Open:

```text
http://127.0.0.1:5173/
```

Build:

```bash
cd frontend
npm run build
```

## Tests

Backend full suite:

```bash
python3 -m pytest -q
```

Focused anti-drift suite:

```bash
python3 -m pytest tests/test_healthcare_anti_drift.py -q
```

Research and progress checks:

```bash
python3 -m pytest tests/test_research_view_model.py tests/test_progress_stages.py -q
```

Pricing checks:

```bash
python3 -m pytest tests/test_pricing.py tests/test_pricing_driver_closure.py tests/test_source_truth_pricing_compiler.py -q
```

## Useful Environment Settings

Do not commit secrets. Use environment variables or local `.env`.

Common settings:

- `ARCHWAY_DATA_DIR`: artifact/session directory.
- `ARCHWAY_DIAGRAM_COMPILER_PATH`: existing D2 compiler source path.
- `ARCHWAY_COMPILER_TOTAL_TIMEOUT_SECONDS`
- `ARCHWAY_ENABLE_WEB_SEARCH`
- `ARCHWAY_ENABLE_COMPETITOR_WEB_SEARCH`
- `ARCHWAY_TAVILY_API_KEY` or `ARCHWAY_TAVILY_MCP_URL`
- `ARCHWAY_TAVILY_MAX_CALLS_PER_SESSION`
- `ARCHWAY_ENABLE_AWS_DOCS_MCP`
- `ARCHWAY_AWS_DOCS_MCP_URL`
- `ARCHWAY_ENABLE_AWS_PRICING_MCP`
- `ARCHWAY_AWS_PRICING_MCP_URL` or command/args settings for the AWS Labs pricing MCP server.
- `ARCHWAY_LLM_PROVIDER`
- `ARCHWAY_BEDROCK_REGION`
- `ARCHWAY_BEDROCK_MODEL_ID`

## API Smoke Flow

Minimal smoke flow:

1. `POST /api/sessions`
2. `POST /api/sessions/{session_id}/synthesis/proceed`
3. `POST /api/sessions/{session_id}/research/run`, poll job.
4. `GET /api/sessions/{session_id}/research/report`
5. `POST /api/sessions/{session_id}/architecture/generate`, poll job.
6. `GET /api/sessions/{session_id}/architecture`
7. `POST /api/sessions/{session_id}/diagrams/generate`, poll job.
8. `GET /api/sessions/{session_id}/diagrams`
9. `GET /api/sessions/{session_id}/diagnostics`
10. `GET /api/sessions/{session_id}/export/package`

## Local Environment Warning

Diagram generation and model/MCP checks are environment-sensitive. A failed health check can mean missing local configuration rather than broken application logic.

