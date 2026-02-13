# Observability (Prometheus + Grafana)

## Quick start (local)
```bash
docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d
```

- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (admin / admin)
- API metrics: http://localhost:8080/metrics
- Analytics JSON proxy: http://localhost:3333
- Compliance Live Feed JSON: http://localhost:3334

## Prometheus scrape config (snippet)
```yaml
scrape_configs:
  - job_name: "shopsquire"
    metrics_path: "/metrics"
    static_configs:
      - targets: ["api:8080"]
```

## Grafana provisioning
- Datasource: `config/observability/grafana/datasources/datasource.yml`
- Dashboards: `config/observability/grafana/dashboards/shopsquire-dashboard.json`
  - Includes Prometheus panels + JSON datasource panels (orders/decisions/security daily).
  - Includes Compliance Live Feed table sourced from `/api/v1/admin/compliance/live-feed`.
- Alerting rules: `config/observability/grafana/alerting/control_failures.yml`
- BI Views dashboard: `config/observability/grafana/dashboards/shopsquire-bi-views.json`
  - Uses the Postgres datasource to query BI views.

## BI views (Postgres)
Apply views from: `db/views/shopSquire_bi_views.sql`

## KEV update automation
- Script: `scripts/update_kev_catalog.py`
- Cron sample: `config/observability/cron/update_kev_cron.txt`

## Panels included
- Decision events per minute
- Incident alerts per minute
- Pricing latency p50/p95
- Tickets created per minute
- Chaos injections
