# Demo Showcase Flow

This guide outlines the end-to-end complaint pipeline demo, highlighting metrics and bitemporal decision logs.

## Prereqs
- Virtualenv created and activated
- `python-multipart` installed for file uploads
- Optional: Ollama running (127.0.0.1:11434) with `llava` and `llama3:8b`

## Start API (SQLite demo)
Set demo-friendly envs and start FastAPI via Uvicorn:

```
$env:DATABASE_URL = "sqlite+pysqlite:///$PWD/tmp/e2e.sqlite"
$env:DISABLE_UI_ROUTES = "0"
$env:API_PORT = "8081"
$env:BACKPRESSURE_TEST_DELAY_SEC = "0.3"
& ".venv/Scripts/python.exe" -m uvicorn src.app.main:create_app --host 127.0.0.1 --port 8081 --factory
```

## Demo Steps
1) Submit Complaint (with image)
- Endpoint: POST /api/v1/support/complaints/submit
- Behavior:
  - Image sanitization (MIME, EXIF strip, SHA256, phash)
  - Managed CV provider labels/text (`cv_analyses` persisted)
  - Fraud enrichment (serial mismatch vs expected order serial, phash DB lookup)
  - Decision log captures `fraud_signals` in `retrieved_context`

2) Add Images
- Endpoint: POST /api/v1/support/complaints/{case_id}/add-images
- Behavior:
  - Second CV call produces labels/text; persisted analysis rows

3) Warehouse Verification
- Service: `WarehouseVerification.compare_latest_pair(case_id)`
- Outputs mismatches (`labels_overlap_low`, `damage_location`, `confidence_delta_high`)

4) Return Label (stub)
- Endpoint: GET /api/v1/support/complaints/{case_id}/return-label
- Behavior: generates a tracking number + label URL; decision log recorded by notification agent

5) Security Escalation (optional)
- Endpoint: POST /api/v1/admin/security/events/{id}/escalate | /block
- Behavior: incident creation + ticketing; bitemporal decision logs for `security_escalation_agent` and `ticketing_agent`

## Decision Logs
- Table: `decision_logs` (bitemporal fields valid/system from/to)
- Sample queries:

```
SELECT agent_name, input_data, proposed_action, system_from
FROM decision_logs
ORDER BY system_from DESC
LIMIT 20;

-- Fraud signals on first complaint decision
SELECT json_extract(retrieved_context, '$.fraud_signals') AS fraud
FROM decision_logs
WHERE json_extract(input_data, '$.case_id') = :case_id
ORDER BY system_from ASC
LIMIT 1;
```

## Metrics & Observability
- Metrics: DB query latency, ticket metrics
- Tracing: OpenTelemetry spans (can be disabled via `DISABLE_TRACING=1`)
- Webhooks: security events emit via `config/webhooks.yml` when configured

## Test Harness
- Pipeline smoke and E2E tests:
  - `tests/api/test_complaints_pipeline_smoke.py`
  - `tests/api/test_pipeline_e2e_fraud_and_warehouse.py`
- Run selectively:

```
& ".venv/Scripts/python.exe" -m pytest -q tests/api/test_pipeline_e2e_fraud_and_warehouse.py
```