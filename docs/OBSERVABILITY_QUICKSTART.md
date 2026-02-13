# Observability Quickstart (Prometheus + Grafana + BI Exports)

## Docker (recommended)

Bring up API + Postgres + Redis + Prometheus + Grafana:

- `docker compose up -d --build`

Key URLs (defaults):

- API: `http://localhost:8080`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3005` (mapped from container `:3000` to avoid conflicts with frontend dev servers)

## Scheduled sync worker (hands-off demo)

`docker-compose.yml` includes a `sync-worker` service that runs `scripts/sync_worker.py` on an interval.

Environment knobs (in compose or `.env`):

- `INVENTORY_SYNC_CONNECTORS` (default `csv,shopify`)
- `INVENTORY_SYNC_INTERVAL_SEC` (default `300`)
- `INVENTORY_SYNC_DRY_RUN` (default `0`)
- `INVENTORY_SYNC_UPSERT_PRODUCTS` (default `0`)

## Metrics

- Prometheus scrape target: API `/metrics`
- Local check: `http://localhost:8080/metrics`

## Grafana

Dashboards are provisioned from:

- `config/observability/grafana/dashboards`

Admin UI embeds dashboards via the backend proxy:

- Admin React: `src/frontend/admin-react/` (dev server)
- Page: **Grafana Observability**

## PowerBI / BI exports

Owner/Developer-only CSV/NDJSON exports (for demos and BI tools):

- `GET /api/v1/admin/powerbi/export.csv`
- `GET /api/v1/admin/powerbi/export.ndjson`
- `GET /api/v1/admin/powerbi/export/decisions.csv`
- `GET /api/v1/admin/powerbi/export/orders.csv`
- `GET /api/v1/admin/powerbi/export/security.csv`

These endpoints are suitable for PowerBI “Web” connectors or scheduled pulls.

## Inventory sync (CSV / Shopify)

Admin API (owner/dev only):

- `POST /api/v1/admin/inventory/sync` with `{ "connector": "csv", "dry_run": false }`

CLI job (useful for cron/Task Scheduler):

- `python scripts/run_inventory_sync.py --connector csv --dry-run`
- `python scripts/run_inventory_sync.py --connector csv`
- `python scripts/run_inventory_sync.py --connector shopify`
