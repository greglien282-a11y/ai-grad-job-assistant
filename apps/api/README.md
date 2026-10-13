# Pathwise API

M1-1A adds PostgreSQL persistence services and versioned migrations.
See [persistence setup and rules](../../docs/M1_1A_PERSISTENCE.md).

M1-1B-1 adds authenticated experience HTTP contracts, integer fact versions,
export/delete and PostgreSQL-backed API tests. See [API setup and contracts](../../docs/M1_1B_1_API.md).
Use `python -m app` for the local API (loads `apps/api/.env`, disables access logs).

Requires Python 3.11+.

```bash
cd apps/api
python -m venv .venv
# On Windows: .venv\\Scripts\\activate
# On macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m app
```

API: http://127.0.0.1:8000/api/v1/health (returns `{"status":"ok"}`)

OpenAPI documentation: http://127.0.0.1:8000/docs

Test in `apps/api`:

```bash
python -m pytest -q
```

For development CORS, copy the root `.env.example` to `apps/api/.env` or export
`CORS_ORIGINS`. Set DATABASE_URL and run `alembic upgrade head` before business calls.
No AI generation exists. Health checks still work without a database.
