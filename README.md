# Archway

Archway is a local-first AWS solution architecture assistant. It turns a rough AI use case into a structured brief, research report, deterministic pricing estimate, POC and production architecture specs, and diagrams generated through the existing local Archway Diagram Compiler.

## Run Locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e "../Archway Diagram Compiler"
uvicorn app.main:app --reload --port 8000
```

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

## Security Defaults

- Secrets stay server-side and are never returned by health or diagnostics APIs.
- Tool calls are allowlisted, phase-scoped, and read-only by default.
- Artifacts are stored under `.archway/sessions/<session_id>` and served only through path-safe artifact IDs.
- Pricing is calculated by code and every line carries evidence metadata.
- Research separates assumptions, evidence, and recommendations.
- Diagrams are generated only through the existing local Archway Diagram Compiler.

