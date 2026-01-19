# Metrics and Prometheus Scrape

## Endpoint
- The API exposes Prometheus metrics at `/metrics`.
- Counters and histograms include:
  - `shopsquire_incident_alerts_total{topic,severity}`
  - `shopsquire_tickets_created_total{topic,priority}`
  - `shopsquire_pricing_latency_seconds_bucket`, `_sum`, `_count`
  - `shopsquire_chaos_injected_total{latency_ms}`

## Sample prometheus.yml
```yaml
scrape_configs:
  - job_name: shopsquire
    scrape_interval: 15s
    metrics_path: /metrics
    static_configs:
      - targets: ["localhost:8080"]
```

## Grafana
- Import `config/observability/grafana_dashboard.json`.
- Set Prometheus as a data source; the panels reference the metric names above.

## Notes
- In local/test, `DECISION_LOG_WRITES_ENABLED=false` avoids DB writes; metrics still work.
- Chaos injection metrics increment when `CHAOS.enabled=true` and probability thresholds are met.
