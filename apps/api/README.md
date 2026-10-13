# Pathwise API (M1-0)

M1-1A adds PostgreSQL persistence services and versioned migrations. Business HTTP
endpoints are deferred to M1-1B. See [persistence setup and rules](../../docs/M1_1A_PERSISTENCE.md).

Requires Python 3.11+.

```bash
cd apps/api
python -m venv .venv
# On Windows: .venv\\Scripts\\activate
# On macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

API: http://127.0.0.1:8000/api/v1/health (returns `{"status":"ok"}`)

OpenAPI documentation: http://127.0.0.1:8000/docs

Test in `apps/api`:

```bash
python -m pytest -q
```

For development CORS, optionally copy the root `.env.example` and export `CORS_ORIGINS`. No authentication, AI generation, or persistent user data exists in this milestone.
