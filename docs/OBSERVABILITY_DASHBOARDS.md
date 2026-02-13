# Observability Dashboards & Alerting

## Prometheus + Alertmanager
- Prometheus config: see `config/observability/prometheus.yml`. Rule files are loaded from `/etc/prometheus/rules/*.yml`.
- Alertmanager config: see `config/observability/alertmanager.yml` (routes/receivers).
- Prometheus alert rules: `config/observability/rules/shopsquire-core.yml` includes drift, WS disconnects, incident spikes, and human review backlog.

## Grafana
- Datasources and dashboards are provisioned from `config/observability/grafana/*`.
- Executive overview and feature dashboards live under `config/observability/grafana/dashboards/`.
- JSON datasource services (`grafana-json`, `grafana-livefeed`) proxy API `/metrics` and decision streams for panel rendering.

## Metrics Wiring Guide
- LLM: `shopsquire_llm_tokens_total`, `shopsquire_llm_latency_seconds`, `shopsquire_model_selection_total`.
- Agents: `shopsquire_agent_confidence`, `shopsquire_agent_escalations_total`.
- CV: `shopsquire_cv_processing_seconds`, `shopsquire_cv_tier_selection_total`.
- Human Review: `human_review_queued`, `human_review_completed`, `human_review_latency_s`.
- WS: `shopsquire_ws_disconnects_total` from decisions WS endpoints.

## Importing Dashboards
1. Start the stack: `docker-compose -f docker-compose.observability.yml up -d`.
2. Grafana at `http://localhost:3000` (admin/admin).
3. Import dashboards from provisioning or upload JSON files.

## Alert Routing
- Prometheus evaluates rule files and sends alerts to Alertmanager (`alertmanagers` section).
- Configure receivers in `config/observability/alertmanager.yml` (email, webhook, Slack, etc.).
