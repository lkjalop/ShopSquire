port 8080 Archive (Deprecated)
==============================

As of February 22, 2026, local runtime defaults are canonicalized to port `8080`.

Canonical local ports:
- Frontend dev server: `5173`
- API/backend (FastAPI): `8080`
- Grafana (optional): `3005`

Notes:
- Legacy `8081` references were retained only in historical docs outside active runtime paths.
- Active scripts/tests/frontends now default to `8080` to avoid connection drift.
